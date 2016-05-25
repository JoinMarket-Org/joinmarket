# texttable-python.  ( https://github.com/dan-da/texttable-python )
# author:  Dan Libby.  https://github.com/dan-da/

from collections import OrderedDict

class ttrow(OrderedDict):
    pass

#
# A class to print text in formatted tables.
#
class texttable:


    # Formats a fixed-width text table, with borders.
    #
    # param rows  array of rows.  each row contains array or ttrow (key/val)
    # param headertype  keys | firstrow | none/None 
    # param footertype  keys | lastrow | none/None
    # param empty_row_string  String to use when there is no data, or None.
    @classmethod
    def table( cls, rows, headertype = 'keys', footertype = 'none', empty_row_string = 'No Data' ):
        
        if not len( rows ):
            if( empty_row_string != None ):
                rows = [ [ empty_row_string ] ]
            else:
                return ''
        
        header = footer = None
        if( headertype == 'keys' and isinstance(rows[0], dict)):
            header = cls.obj_arr( rows[0] ).keys()
        elif( headertype == 'firstrow' ):
            header = cls.obj_arr( rows[0] )
            rows = rows[1:]
        if( footertype == 'keys' and len( rows ) and isinstance(rows[len(rows)-1],dict) ):
            footer = cls.obj_arr( rows[len(rows) - 1] ).keys()
        elif( footertype == 'lastrow' and len( rows ) ):
            footer = cls.obj_arr( rows[len(rows)-1] )
            rows = rows[:-1]
                
        col_widths = {}
        
        if( header ):
            cls.calc_row_col_widths( col_widths, header )
        if( footer ):
            cls.calc_row_col_widths( col_widths, footer )
        for row in rows:
            row = cls.obj_arr( row )
            cls.calc_row_col_widths( col_widths, row )
            
        buf = ''
        if( header ):        
            buf += cls.print_divider_row( col_widths )
            buf += cls.print_row( col_widths, header )
        buf += cls.print_divider_row( col_widths )
        for row in rows:
            row = cls.obj_arr( row )
            buf += cls.print_row( col_widths, row )
        buf += cls.print_divider_row( col_widths )
        if( footer ):        
            buf += cls.print_row( col_widths, footer )
            buf += cls.print_divider_row( col_widths )
                
        return buf
        
    @classmethod
    def print_divider_row( cls, col_widths ):
        buf = '+'
        for i in range(0, len(col_widths)):
            width = col_widths[i]
            buf += '-' + '-'.ljust( width, '-' ) + "-+"
        buf += "\n"
        return buf
    
    @classmethod
    def print_row( cls, col_widths, row ):
        buf = '|'
        idx = 0
        for val in row:
            
            if isinstance(row, dict):
                val = row[val]
            val = str(val)
                
            pad_type = 'left' if cls.is_numeric( val ) else 'right'
            if pad_type == 'left':
                buf += ' ' + val.rjust( col_widths[idx], ' ' ) + " |"
            else:
                buf += ' ' + val.ljust( col_widths[idx], ' ' ) + " |"
            idx = idx + 1
        return buf + "\n"
    
    @classmethod
    def calc_row_col_widths( cls, col_widths, row ):
        idx = 0
        
        for val in row:

            if isinstance(row, dict):
                val = row[val]
            val = str(val)
            
            if idx not in col_widths:
                col_widths[idx] = 0
            if( len(val) > col_widths[idx] ):
                col_widths[idx] = len(val)
            idx = idx + 1
                
    @classmethod
    def obj_arr( cls, t ):
        return t
        return dir( t ) if isinstance( t, object ) else t
    
    @classmethod
    def is_numeric(cls, var):
        try:
            float(var)
            return True
        except ValueError:
            return False    
    
